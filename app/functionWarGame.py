import numpy as np
import random
import math

STILL = 0
UP = 1
DOWN = 2
LEFT = 3
RIGHT = 4


def transformIndexToX(index, mapSize):
    return int(index/mapSize[1])

def transformIndexToY(index, mapSize):
    return index % mapSize[1]


def transformSoldierToSoldierPolicy(soldiers, warField, AorB):
    result = [soldiers[i] if warField[i] == AorB else 0 for i in range(len(warField))]
    return result

def kaigenhaochengshi(list):
    result = [math.sqrt(list[i])*10 for i in range(len(list))]
    return result

def concatenate_unique_lists(list1, list2):
    # 将两个列表合并成一个，并使用set去除重复元素
    result = list(set(list1 + list2))
    return result
def find_common_elements(list1, list2):
    # 使用集合的交集操作找到两个列表的共有元素
    common_elements = list(set(list1) & set(list2))
    return common_elements

def elements_only_in_first_list(list1, list2):
    # 使用列表推导式找到只在第一个列表中而不在第二个列表中的元素
    unique_elements = [element for element in list1 if element not in list2]
    return unique_elements

def transformToIndexList(posListA, mapSize):
    result = []
    for i in range(len(posListA)):
        if int(posListA[i][0] / mapSize[1]) == int(posListA[i][1] / mapSize[1]):
            indexListA = [min(posListA[i][0], posListA[i][1]) + x for x in
                          range(int(abs(posListA[i][0] - posListA[i][1])) + 1)]
        if abs(posListA[i][0] - posListA[i][1]) % mapSize[1] == 0:
            indexListA = [min(posListA[i][0], posListA[i][1]) + x * mapSize[1] for x in
                         range(int(abs(posListA[i][0] - posListA[i][1]) / mapSize[1]) + 1)]
        result = concatenate_unique_lists(result, indexListA)
    return result

def transformToIndexListOne(posListA, mapSize):
    indexListA = []
    if int(posListA[0] / mapSize[1]) == int(posListA[1] / mapSize[1]):
        indexListA = [min(posListA[0], posListA[1]) + x for x in
                      range(int(abs(posListA[0] - posListA[1])) + 1)]
    if abs(posListA[0] - posListA[1]) % mapSize[1] == 0:
        indexListA = [min(posListA[0], posListA[1]) + x * mapSize[1] for x in
                     range(int(abs(posListA[0] - posListA[1]) / mapSize[1]) + 1)]
    return indexListA

def transformTempListToInt(tempList):
    if len(tempList) >0:
        number = '0'
        for i in range(len(tempList)):
            number = number + str(tempList[i])
        return int(number)
    else: return 0


def judgeResult(remainingSoldiersA, remainingSoldiersB, warField):
    warFieldNew = [0 for i in range(len(warField))]
    for i in range(len(warField)):
        if remainingSoldiersA[i] > 0:
            warFieldNew[i] = 1
        elif remainingSoldiersB[i] > 0:
            warFieldNew[i] = 2
        elif remainingSoldiersB[i] == 0 and remainingSoldiersA[i] == 0:
            warFieldNew[i] = warField[i]
    return warFieldNew


def transformPolicyToSoldierMove(policy):
    soldierMove = [0 for i in range(len(policy))]
    if policy.count(1) >0:
        index = policy.index(1)

        for i in range(len(policy)):
            if i < index:
                soldierMove[i] = 1
            if i == index:
                soldierMove[i] = 0
            if i > index:
                soldierMove[i] = -1
        return soldierMove
    else:
        return soldierMove

def calculateWinner(soldiersA, soldiersB):
    ratio = soldiersA/(soldiersA+soldiersB)
    coin = random.uniform(0,1)
    # print(coin)
    if coin < ratio:
        return 1
    else:
        return 2

def calculateLostRate(soldiersA, soldiersB):
    factorA = 0.02
    factorB = 0.8
    if soldiersA < 1:
        return [1, 0]
    if soldiersB < 1:
        return [0, 1]
    if soldiersB >= soldiersA:
        lostRateA = factorA * math.exp(factorB*(soldiersB / soldiersA - 1))
        lostRateB = factorA * math.exp(factorB*(1 - soldiersB / soldiersA))
    else:
        lostRateA = factorA * math.exp(factorB*(1 - soldiersA / soldiersB))
        lostRateB = factorA * math.exp(factorB*(soldiersA / soldiersB - 1))
    return [min(lostRateA,1), min(lostRateB,1)]

def simulateWarProcess(soldiersA, soldiersB):
    lostLimit = 0.7
    initialSoldiersA = soldiersA
    initialSoldiersB = soldiersB

    while True:
        lostRate = calculateLostRate(soldiersA, soldiersB)
        lamdaA = max(round(soldiersA*lostRate[0]), 1)
        lamdaB = max(round(soldiersB*lostRate[1]), 1)
        lostSoldierA = np.random.poisson(lamdaA, 1)
        lostSoldierB = np.random.poisson(lamdaB, 1)
        soldiersA -= lostSoldierA[0]
        soldiersB -= lostSoldierB[0]
        soldiersA = max(soldiersA, 0)
        soldiersB = max(soldiersB, 0)
        if soldiersB == 0:
            # print('B empty')
            return soldiersA, soldiersB, 1
        elif soldiersA == 0:
            # print('A empty')
            return soldiersA, soldiersB, 2
        if soldiersA/initialSoldiersA < lostLimit and soldiersB/initialSoldiersB >= lostLimit:
            return soldiersA, soldiersB, 2
        if soldiersA/initialSoldiersA >= lostLimit and soldiersB/initialSoldiersB < lostLimit:
            return soldiersA, soldiersB, 1
        if soldiersA / initialSoldiersA < lostLimit and soldiersB / initialSoldiersB < lostLimit:
            return soldiersA, soldiersB, calculateWinner(soldiersA, soldiersB)

def simulateWinningRate(soldiersA, soldiersB):
    simulateRound = 100
    lostListA = []
    lostListB = []
    outcomeList = []
    for i in range(simulateRound):
        remainingSoldiersA, remainingSoldiersB, winner = simulateWarProcess(soldiersA, soldiersB)
        outcomeList.append(winner)
        lostRateA = (soldiersA - remainingSoldiersA)/soldiersA
        lostRateB = (soldiersB - remainingSoldiersB)/soldiersB
        lostListA.append(lostRateA)
        lostListB.append(lostRateB)
    winningRateA = outcomeList.count(1) / simulateRound
    return np.mean(lostListA), np.mean(lostListB), winningRateA


def calculateIndividualSoldiers(warField, soldiers, index):
    result = 0
    for i in range(len(warField)):
        if warField[i] == index:
            result += soldiers[i]

    return result

def transformIntToTempList(integer):
    tempList = []
    while(integer > 0):
        tempList.append(integer%10)
        integer = int(integer / 10)
    tempList.reverse()
    return tempList

def transformCoordinateToIndex(pos, coordinateList, cubeWidth):
    for i in range(len(coordinateList)):
        if 0 <= pos[0]-coordinateList[i][0] <= cubeWidth and 0 <= pos[1]-coordinateList[i][1] <= cubeWidth:
            return i

    return -1

def calculate2DDistance(index1, index2, mapSize):
    x1 = transformIndexToX(index1, mapSize)
    x2 = transformIndexToX(index2, mapSize)
    y1 = transformIndexToY(index1, mapSize)
    y2 = transformIndexToY(index2, mapSize)
    return abs(x1-x2)+abs(y1-y2)

def findTheNearest(index, defendList, mapSize):
    distance = [calculate2DDistance(index, defendList[i], mapSize) for i in range(len(defendList))]
    return defendList[distance.index(min(distance))]

def calculateRelativeLocation(index, relativeIndex, mapSize):
    if transformIndexToX(relativeIndex, mapSize) > transformIndexToX(index, mapSize) and transformIndexToY(relativeIndex, mapSize) > transformIndexToY(index, mapSize):
        return [RIGHT, DOWN]
    if transformIndexToX(relativeIndex, mapSize) > transformIndexToX(index, mapSize) and transformIndexToY(relativeIndex, mapSize) == transformIndexToY(index, mapSize):
        return [DOWN]
    if transformIndexToX(relativeIndex, mapSize) > transformIndexToX(index, mapSize) and transformIndexToY(relativeIndex, mapSize) < transformIndexToY(index, mapSize):
        return [LEFT, DOWN]

    if transformIndexToX(relativeIndex, mapSize) == transformIndexToX(index, mapSize) and transformIndexToY(relativeIndex, mapSize) > transformIndexToY(index, mapSize):
        return [RIGHT]
    if transformIndexToX(relativeIndex, mapSize) == transformIndexToX(index, mapSize) and transformIndexToY(relativeIndex, mapSize) == transformIndexToY(index, mapSize):
        return [STILL]
    if transformIndexToX(relativeIndex, mapSize) == transformIndexToX(index, mapSize) and transformIndexToY(relativeIndex, mapSize) < transformIndexToY(index, mapSize):
        return [LEFT]

    if transformIndexToX(relativeIndex, mapSize) < transformIndexToX(index, mapSize) and transformIndexToY(relativeIndex, mapSize) > transformIndexToY(index, mapSize):
        return [RIGHT, UP]
    if transformIndexToX(relativeIndex, mapSize) < transformIndexToX(index, mapSize) and transformIndexToY(relativeIndex, mapSize) == transformIndexToY(index, mapSize):
        return [UP]
    if transformIndexToX(relativeIndex, mapSize) < transformIndexToX(index, mapSize) and transformIndexToY(relativeIndex, mapSize) < transformIndexToY(index, mapSize):
        return [LEFT, UP]

def mergeDirection(directionList, tempList):
    result = []
    defendLineBelong = []
    for i in range(len(directionList)):
        temp1 = directionList[i]
        temp2 = tempList[i]
        for j in range(len(temp2)):
            if temp2[j] in temp1:
                defendLineBelong.append([i, temp1.index(temp2[j])])
            if not temp2[j] in temp1:
                temp1. append(temp2[j])
                defendLineBelong.append([i, len(temp1)-1])
        result.append(temp1)
    return result, defendLineBelong

def unfold(indexList, directionList, defendLineBelongList):
    indexUnfold = []
    directionUnfold = []
    defendLineUnfold = [[] for i in range(len(defendLineBelongList))]
    for i in range(len(directionList)):
        for j in range(len(directionList[i])):
            indexUnfold.append(indexList[i])
            directionUnfold.append(directionList[i][j])
            for k in range(len(defendLineBelongList)):
                if [i,j] in defendLineBelongList[k]:
                    defendLineUnfold[k].append(len(indexUnfold)-1)

    return indexUnfold, directionUnfold, defendLineUnfold



def checkDirections(j, directions, warField, AorB, mapSize, target):
    result = [directions[i] for i in range(len(directions))]
    for direction in result:
        if direction == RIGHT:
            if warField[j + 1] == AorB and not j + 1 == target:
                directions.remove(RIGHT)
        if direction == LEFT:
            if warField[j - 1] == AorB and not j - 1 == target:
                directions.remove(LEFT)

        if direction == UP:
            if warField[j - mapSize[0]] == AorB and not j - mapSize[0] == target:
                directions.remove(UP)
        if direction == DOWN:
            if warField[j + mapSize[0]] == AorB and not j + mapSize[0] == target:
                directions.remove(DOWN)
    return directions



def generateDirectionA(posList, warField, mapSize):

    directionList = []
    indexList = []
    defendLineBelongList = []
    defendLineBelong = []
    defendList = []
    for i in range(len(posList)):
        defendList = [posList[i]]
        if len(defendList) == 0:
            return [], [], []
        tempList = []
        for j in range(len(warField)):
            if warField[j] == 1:
                # tempList.append(calculateRelativeLocation(j, findTheNearest(j, defendList, mapSize), mapSize))
                tempList.append(checkDirections(j, calculateRelativeLocation(j, findTheNearest(j, defendList, mapSize), mapSize), warField, 2, mapSize, findTheNearest(j, defendList, mapSize)))
                if i == 0:
                    indexList.append(j)
        if i == 0:
            directionList = tempList
        directionList, defendLineBelong = mergeDirection(directionList, tempList)
        defendLineBelongList.append(defendLineBelong)

    indexList, directionList, defendLineBelongList = unfold(indexList, directionList, defendLineBelongList)

    return indexList, directionList, defendLineBelongList

def generateDirectionB(posList, warField, mapSize):

    directionList = []
    indexList = []
    defendLineBelongList = []
    defendLineBelong = []
    defendList = []
    for i in range(len(posList)):
        defendList = [posList[i]]
        if len(defendList) == 0:
            return [], [], []
        tempList = []
        for j in range(len(warField)):
            if warField[j] == 2:
                # tempList.append(calculateRelativeLocation(j, findTheNearest(j, defendList, mapSize), mapSize))
                tempList.append(
                    checkDirections(j, calculateRelativeLocation(j, findTheNearest(j, defendList, mapSize), mapSize),
                                    warField, 1, mapSize, findTheNearest(j, defendList, mapSize)))
                if i == 0:
                    indexList.append(j)
        if i == 0:
            directionList = tempList
        directionList, defendLineBelong = mergeDirection(directionList, tempList)
        defendLineBelongList.append(defendLineBelong)

    indexList, directionList, defendLineBelongList = unfold(indexList, directionList, defendLineBelongList)

    return indexList, directionList, defendLineBelongList

def findCurrentBaseIndex(mapSize, warField, AorB):
    currentIndexSet = []
    for i in range(len(warField)):
        if warField[i] == AorB:
            currentIndexSet.append(i)
    if len(currentIndexSet) == 0:
        return 0
    distanceList = []
    for i in range(len(currentIndexSet)):
        distance = 0
        for j in range(len(currentIndexSet)):
            distance += calculate2DDistance(currentIndexSet[i], currentIndexSet[j], mapSize)
        distanceList.append(distance)
    return currentIndexSet[distanceList.index(min(distanceList))]

def calculateLogisticRate(index, baseIndex, mapSize, warField, AorB):
    constant = 6
    currentBase = findCurrentBaseIndex(mapSize, warField, AorB)

    distance = calculate2DDistance(index, currentBase, mapSize)

    if (constant - distance) <= 0:
        return 0

    return 0

def calculateTowardList(indexList, directionList, mapSize):
    result = []
    for i in range(len(indexList)):
        if directionList[i] == UP:
            result.append(indexList[i]-mapSize[1])
        if directionList[i] == DOWN:
            result.append(indexList[i] + mapSize[1])
        if directionList[i] == LEFT:
            result.append(indexList[i] - 1)
        if directionList[i] == RIGHT:
            result.append(indexList[i] + 1)
        if directionList[i] == STILL:
            result.append(indexList[i])

    return result

def normalize(list):
    if list == [] or sum(list) == 0:
        return []
    result = [list[i]/sum(list) for i in range(len(list))]
    return result

def normalize01(list):
    if list == [] or sum(list) == 0:
        return []

    result = [list[i]/sum(list) for i in range(len(list))]

    for i in range(len(result)):
        if result[i] > 0:
            result[i] = 0.5
        else:
            result[i] = 0

    return result


def normalizeForPolicy(list):
    if sum(list) == 0:
        return list
    result = [list[i]/sum(list) for i in range(len(list))]
    return result

def normalizeAll(list):
    sumList = [sum(list[i]) for i in range(len(list))]
    for i in range(len(sumList)):
        if sumList[i] == 0:
            sumList[i] =1
    result = [[list[i][j]/sumList[i] for j in range(len(list[i]))] for i in range(len(list))]
    return result

def normalizeOverall(list):
    sumList = [sum(list[i]) for i in range(len(list))]
    sumAll = sum(sumList)
    result = [[list[i][j]/sumAll for j in range(len(list[i]))] for i in range(len(list))]
    return result


def normalizeToPercent(list):
    if list == [] or sum(list) == 0:
        return [33, 33, 33]
    result = [int(list[i]/sum(list)*100) for i in range(len(list))]
    return result


def linearProgramingA(mapSize, soldiers, indexList, directionList):
    moveLength = len(directionList)
    towardList = calculateTowardList(indexList, directionList, mapSize)
    soldiersMove = [round(soldiers[indexList[i]]/indexList.count(indexList[i])) for i in range(len(indexList))]
    return soldiersMove, towardList

def linearProgramingB(mapSize, soldiers, indexList, directionList):
    moveLength = len(directionList)
    towardList = calculateTowardList(indexList, directionList, mapSize)
    soldiersMove = [round(soldiers[indexList[i]] / indexList.count(indexList[i])) for i in range(len(indexList))]
    return soldiersMove, towardList


def moveSoldiers(soldiersMove, towardList, warField):
    soldierPolicy = [0 for i in range(len(warField))]
    for i in range(len(towardList)):
        soldierPolicy[towardList[i]] += soldiersMove[i]

    soldierPolicy = [round(soldierPolicy[i]) for i in range(len(warField))]

    return soldierPolicy


def isAdjacent(index, indexSubset, mapSize):

    for i in range(len(indexSubset)):
        x1 = transformIndexToX(index, mapSize)
        x2 = transformIndexToX(indexSubset[i], mapSize)
        y1 = transformIndexToY(index, mapSize)
        y2 = transformIndexToY(indexSubset[i], mapSize)
        if abs(x1-x2) + abs(y1-y2) == 1:
            return 1

    return 0

def addWarParts(index, warParts, mapSize):
    maximalParts = 6
    for i in range(len(warParts)):
        if len(warParts[i]) < maximalParts and isAdjacent(index, warParts[i], mapSize):
            warParts[i].append(index)
            return warParts

    warParts.append([index])
    return warParts


def generateWarParts(warLocation, mapSize):
    if warLocation == []:
        return []
    warParts = [[warLocation[0]]]
    for i in range(len(warLocation)-1):
        warParts = addWarParts(warLocation[i+1], warParts, mapSize)
    return warParts

# def computeAdjacent(binaryIndex):
#     return abs(binaryIndex.count(1) - binaryIndex.count(0))

def computeAdjacent(binaryIndex, warParts, mapSize):
    adjacentList = [[] for _ in range(len(warParts))]
    for i in range(len(warParts)):
        for j in range(len(warParts)):
            if isAdjacent(warParts[i], [warParts[j]], mapSize):
                adjacentList[i].append(j)

    adjacentGrids = 0
    for i in range(len(binaryIndex)):
        for j in range(len(adjacentList[i])):
            if binaryIndex[i] == binaryIndex[adjacentList[i][j]]:
                adjacentGrids += 1
    return adjacentGrids/2

def generateWinnerList(winningRateAList, warParts, mapSize):
    binary = lambda n: "" if n == 0 else binary(n // 2) + str(n % 2)

    correlationRate = 2**(1/len(warParts))

    result = [0 for i in range(2**len(winningRateAList))]
    distribution = []
    distributionIndicator = []
    for i in range(len(result)):
        x = 1
        binaryIndex = list(map(int, binary(i)))
        while len(binaryIndex) < len(winningRateAList):
            binaryIndex.insert(0,0)
        for j in range(len(winningRateAList)):
            x = x*(winningRateAList[j]**binaryIndex[j])*((1-winningRateAList[j])**(1-binaryIndex[j]))
        adjacent = computeAdjacent(binaryIndex, warParts, mapSize)
        x = x * correlationRate**adjacent
        distribution.append(x)
        distributionIndicator.append(binaryIndex)
    distribution[0] = distribution[0]*correlationRate
    distribution[-1] = distribution[-1]*correlationRate
    distribution = normalize(distribution)
    # print(distribution)
    # cumulativeDistribution = []
    temp = 0
    coin = random.uniform(0, 1)
    # print(coin)
    resultIndex = 0
    for i in range(len(distribution)):
        temp += distribution[i]
        if coin < temp:
            resultIndex = i
            break
        # cumulativeDistribution.append(temp)

    return distributionIndicator[resultIndex]

def findRetrieveLocation(index, warLocation, mapSize, AorB):
    if AorB == 1:

        while transformIndexToY(index, mapSize) > 0:
            index -= 1
            if not index in warLocation:
                return index
        if transformIndexToY(index, mapSize) == 0:
            return -1

    if AorB == 2:

        while transformIndexToY(index, mapSize) < (mapSize[1]-1):
            index += 1
            if not index in warLocation:
                return index
        if transformIndexToY(index, mapSize) == (mapSize[1]-1):
            return -1



def simulateWar(soldierPolicyA, soldierPolicyB, mapSize):
    soldierPolicyANew = soldierPolicyA
    soldierPolicyBNew = soldierPolicyB

    warLostA = []
    warLostB = []

    warLocation = []
    for i in range(len(soldierPolicyA)):
        if soldierPolicyA[i] > 0 and soldierPolicyB[i] > 0:
            warLocation.append(i)
    warParts = generateWarParts(warLocation, mapSize)

    for i in range(len(warParts)):
        lostRateAList = []
        lostRateBList = []
        winningRateAList = []
        for j in range(len(warParts[i])):
            lostRateA, lostRateB, winningRateA = simulateWinningRate(soldierPolicyA[warParts[i][j]], soldierPolicyB[warParts[i][j]])
            lostRateAList.append(lostRateA)
            lostRateBList.append(lostRateB)
            warLostA.append(round(soldierPolicyA[warParts[i][j]] * lostRateA))
            soldierPolicyANew[warParts[i][j]] = round(soldierPolicyA[warParts[i][j]] * (1 - lostRateA))

            warLostB.append(round(soldierPolicyB[warParts[i][j]] * lostRateB))
            soldierPolicyBNew[warParts[i][j]] = round(soldierPolicyB[warParts[i][j]] * (1 - lostRateB))

            winningRateAList.append(winningRateA)

        # winnerList = generateWinnerList(winningRateAList)
        winnerList = generateWinnerList(winningRateAList, warParts[i], mapSize)
        for j in range(len(warParts[i])):
            if winnerList[j] == 1:
                retrieveLocation = findRetrieveLocation(warParts[i][j], warLocation, mapSize, 2)
                if retrieveLocation >= 0:
                    soldierPolicyBNew[retrieveLocation] += soldierPolicyBNew[warParts[i][j]]
                soldierPolicyBNew[warParts[i][j]] = 0

            if winnerList[j] == 0:
                retrieveLocation = findRetrieveLocation(warParts[i][j], warLocation, mapSize, 1)
                if retrieveLocation >= 0:
                    soldierPolicyANew[retrieveLocation] += soldierPolicyANew[warParts[i][j]]
                soldierPolicyANew[warParts[i][j]] = 0

    return soldierPolicyANew, soldierPolicyBNew, warLostA, warLostB


def forwardNextStep(soldierPolicyA, soldierPolicyB, warField, mapSize, soldierFromWarFieldA, soldierFromWarFieldB, baseIndexA, baseIndexB):
    warLocation = []
    for i in range(len(warField)):
        if soldierPolicyA[i] > 0 and soldierPolicyB[i] > 0:
            warLocation.append(i)

    soldierPolicyA, soldierPolicyB, warLostA, warLostB = simulateWar(soldierPolicyA, soldierPolicyB, mapSize)

    warFieldNew = [0 for i in range(len(warField))]
    for i in range(len(warFieldNew)):
        if soldierPolicyA[i] > 0:
            warFieldNew[i] = 1
        if soldierPolicyB[i] > 0:
            warFieldNew[i] = 2
        if soldierPolicyA[i] == soldierPolicyB[i] == 0:
            warFieldNew[i] = warField[i]

    soldierPolicyANew = [soldierPolicyA[i]-round(soldierPolicyA[i]*calculateLogisticRate(i, baseIndexA, mapSize, warFieldNew, 1)) for i in range(len(soldierPolicyA))]
    soldierPolicyBNew = [soldierPolicyB[i]-round(soldierPolicyB[i]*calculateLogisticRate(i, baseIndexB, mapSize, warFieldNew, 2)) for i in range(len(soldierPolicyB))]

    logisticsA = sum(soldierPolicyA)-sum(soldierPolicyANew)
    logisticsB = sum(soldierPolicyB)-sum(soldierPolicyBNew)

    for i in range(len(warFieldNew)):
        if warFieldNew[i] == 1:
            soldierPolicyANew[i] = soldierPolicyANew[i] + soldierFromWarFieldA
        if warFieldNew[i] == 2:
            soldierPolicyBNew[i] = soldierPolicyBNew[i] + soldierFromWarFieldB

    # soldierPolicyANew[baseIndexA] = soldierPolicyANew[baseIndexA] + warFieldNew.count(1) * soldierFromWarFieldA
    # soldierPolicyBNew[baseIndexB] = soldierPolicyBNew[baseIndexB] + warFieldNew.count(2) * soldierFromWarFieldB

    soldiersNew = [max(soldierPolicyANew[i], soldierPolicyBNew[i], 0) for i in range(len(soldierPolicyANew))]

    return soldiersNew, warFieldNew, warLocation, warLostA, warLostB, logisticsA, logisticsB

def simulateWarWithLostRate(soldierPolicyA, soldierPolicyB, mapSize):
    soldierPolicyANew = soldierPolicyA
    soldierPolicyBNew = soldierPolicyB

    warLocation = []
    for i in range(len(soldierPolicyA)):
        if soldierPolicyA[i] > 0 and soldierPolicyB[i] > 0:
            warLocation.append(i)
    warParts = generateWarParts(warLocation, mapSize)

    lostRateWinner = []
    lostRateLoser = []

    for i in range(len(warParts)):
        lostRateAList = []
        lostRateBList = []
        winningRateAList = []
        for j in range(len(warParts[i])):
            lostRateA, lostRateB, winningRateA = simulateWinningRate(soldierPolicyA[warParts[i][j]], soldierPolicyB[warParts[i][j]])
            lostRateAList.append(lostRateA)
            lostRateBList.append(lostRateB)
            soldierPolicyANew[warParts[i][j]] = round(soldierPolicyA[warParts[i][j]] * (1 - lostRateA))
            soldierPolicyBNew[warParts[i][j]] = round(soldierPolicyB[warParts[i][j]] * (1 - lostRateB))
            winningRateAList.append(winningRateA)

        winnerList = generateWinnerList(winningRateAList, warParts[i], mapSize)
        for j in range(len(warParts[i])):
            if winnerList[j] == 1:
                retrieveLocation = findRetrieveLocation(warParts[i][j], warLocation, mapSize, 2)
                if retrieveLocation >= 0:
                    soldierPolicyBNew[retrieveLocation] += soldierPolicyBNew[warParts[i][j]]
                soldierPolicyBNew[warParts[i][j]] = 0

            if winnerList[j] == 0:
                retrieveLocation = findRetrieveLocation(warParts[i][j], warLocation, mapSize, 1)
                if retrieveLocation >= 0:
                    soldierPolicyANew[retrieveLocation] += soldierPolicyANew[warParts[i][j]]
                soldierPolicyANew[warParts[i][j]] = 0
        lostRateWinner.append(max(np.mean(lostRateAList), np.mean(lostRateBList)))
        lostRateLoser.append(min(np.mean(lostRateAList), np.mean(lostRateBList)))

    return soldierPolicyANew, soldierPolicyBNew, np.mean(lostRateWinner), np.mean(lostRateLoser)

def forwardNextStepWithLostRate(soldierPolicyA, soldierPolicyB, warField, mapSize):
    currentSoldiers = sum(soldierPolicyA) + sum(soldierPolicyB)
    warLocation = []
    for i in range(len(warField)):
        if soldierPolicyA[i] > 0 and soldierPolicyB[i] > 0:
            warLocation.append(i)

    soldierPolicyA, soldierPolicyB, lostRateWinner, lostRateLoser = simulateWarWithLostRate(soldierPolicyA, soldierPolicyB, mapSize)

    return lostRateWinner, lostRateLoser

def transformPlayerSelectToPosList(playerSelect, mapSize):
    result = []
    for i in range(len(playerSelect)):
        result.append(playerSelect[i][0]*mapSize[0] + playerSelect[i][1])
    return result

def transformShapesToWarField(shapes):
    result = []
    for i in range(len(shapes)):
        for j in range(len(shapes[i])):
            result.append(shapes[i][j])
    return result

def transformNumbersToSoldiers(numbers):
    result = []
    for i in range(len(numbers)):
        for j in range(len(numbers[i])):
            if numbers[i][j] >= 0:
                result.append(numbers[i][j])
            else:
                result.append(0)
    return result

def transformWarFieldToShapes(warField, mapSize):
    result = [[0 for _ in range(mapSize[0])] for _ in range(mapSize[1])]
    for i in range(len(warField)):
        result[transformIndexToX(i, mapSize)][transformIndexToY(i, mapSize)] = warField[i]
    return result

def transformSoldiersToNumbers(soldiers, warField, mapSize):
    result = [[-1 for _ in range(mapSize[0])] for _ in range(mapSize[1])]
    for i in range(len(soldiers)):
        if warField[i] > 0:
            result[transformIndexToX(i, mapSize)][transformIndexToY(i, mapSize)] = soldiers[i]
    return result

def transformWarLocationToCoordinate(warLocation, mapSize):
    result = []
    for i in range(len(warLocation)):
        result.append((transformIndexToX(warLocation[i], mapSize), transformIndexToY(warLocation[i], mapSize)))
    return result

def checkEndGame(shapes):
    warField = transformShapesToWarField(shapes)
    if warField.count(1) == 0 or warField.count(2) == 0:
        return 1
    return 0